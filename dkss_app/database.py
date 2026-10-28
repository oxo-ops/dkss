"""Database responsibilities; routes are registered by the application factory."""
from . import audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization


def init_db():
    with _dkss_runtime.app.app_context():
        _dkss_common.db.create_all()

        # VEHICLE_MAINTENANCE_ATTRIBUTES_MIGRATION
        maintenance_columns = {
            column["name"]
            for column in _dkss_common.inspect(_dkss_common.db.engine).get_columns(_dkss_models.Vehicle.__tablename__)
        }
        maintenance_columns_added = False
        for field_key, field_label, max_length in _dkss_common.VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS:
            if field_key in maintenance_columns:
                continue
            optional = (
                "IF NOT EXISTS "
                if _dkss_common.db.engine.dialect.name == "postgresql" else ""
            )
            statement = (
                f"ALTER TABLE {_dkss_models.Vehicle.__tablename__} ADD COLUMN "
                f"{optional}{field_key} VARCHAR({max_length})"
            )
            _dkss_common.db.session.execute(_dkss_common.db.text(statement))
            maintenance_columns_added = True
        if maintenance_columns_added:
            _dkss_common.db.session.commit()

        public_catalog_columns = {
            column["name"]
            for column in _dkss_common.inspect(_dkss_common.db.engine).get_columns(
                "public_knowledge_catalog"
            )
        }
        if "requested_scope_hash" not in public_catalog_columns:
            if _dkss_common.db.engine.dialect.name == "postgresql":
                statement = (
                    "ALTER TABLE public_knowledge_catalog "
                    "ADD COLUMN IF NOT EXISTS "
                    "requested_scope_hash VARCHAR(64)"
                )
            else:
                statement = (
                    "ALTER TABLE public_knowledge_catalog "
                    "ADD COLUMN requested_scope_hash VARCHAR(64)"
                )
            _dkss_common.db.session.execute(_dkss_common.db.text(statement))
            _dkss_common.db.session.commit()


        inspector = _dkss_common.inspect(_dkss_common.db.engine)

        existing_user_columns = [
            column["name"]
            for column in inspector.get_columns("user")
        ]

        if "last_name" not in existing_user_columns:
            if "name" in existing_user_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        'ALTER TABLE "user" '
                        'RENAME COLUMN name TO last_name'
                    )
                )
            else:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        'ALTER TABLE "user" '
                        'ADD COLUMN last_name VARCHAR(100)'
                    )
                )

            _dkss_common.db.session.commit()
            inspector = _dkss_common.inspect(_dkss_common.db.engine)

        existing_user_columns = [
            column["name"]
            for column in inspector.get_columns("user")
        ]

        if "first_name" not in existing_user_columns:
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    'ALTER TABLE "user" '
                    'ADD COLUMN first_name VARCHAR(100)'
                )
            )
            _dkss_common.db.session.commit()

        _dkss_audit.cleanup_old_audit_logs()

        if not _dkss_models.Company.query.filter_by(company_code="ITC").first():
            _dkss_common.db.session.add(_dkss_models.Company(
                company_code="ITC",
                company_name="ITC",
                vehicle_limit=9999,
                active=True
            ))
            _dkss_common.db.session.commit()

        if not _dkss_models.User.query.filter_by(
            company_code="ITC",
            username="itc"
        ).first():
            initial_password = _dkss_common.os.environ.get(
                "ITC_INITIAL_PASSWORD"
            )

            if not initial_password:
                raise RuntimeError(
                    "ITC_INITIAL_PASSWORD environment variable is required "
                    "when creating the initial ITC administrator."
                )

            _dkss_common.db.session.add(_dkss_models.User(
                company_code="ITC",
                username="itc",
                password=_dkss_common.generate_password_hash(
                    initial_password
                ),
                role="itc",
                last_name="ITC管理者",
                first_name=None,
                office="ITC",
            ))

        default_content_types = [
            "落下",
            "車両",
            "環境",
            "荷扱い",
            "ルール違反",
            "Good",
            "その他"
        ]

        for company in _dkss_models.Company.query.all():
            for name in default_content_types:
                exists = _dkss_models.PatrolContentType.query.filter_by(
                    company_code=company.company_code,
                    name=name
                ).first()

                if not exists:
                    _dkss_common.db.session.add(_dkss_models.PatrolContentType(
                        company_code=company.company_code,
                        name=name
                    ))

        _dkss_common.db.session.commit()
        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_user_company_username "
                'ON "user" (company_code, username)'
            )
        )

        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_driver_company_employee_id "
                "ON driver (company_code, employee_id)"
            )
        )

        duplicate_office = (
            _dkss_common.db.session.query(
                _dkss_models.Office.company_code, _dkss_models.Office.name
            )
            .group_by(_dkss_models.Office.company_code, _dkss_models.Office.name)
            .having(_dkss_common.db.func.count(_dkss_models.Office.id) > 1)
            .first()
        )

        if duplicate_office:
            raise RuntimeError(
                "営業所マスタに同一会社・同一名称の重複があります。"
            )

        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_office_company_name "
                "ON office (company_code, name)"
            )
        )

        for model, label in (
            (_dkss_models.DeliveryPlace, "納入先"),
            (_dkss_models.LicenseType, "免許種別"),
            (_dkss_models.PatrolContentType, "内容区分"),
        ):
            duplicate = (
                _dkss_common.db.session.query(model.company_code, model.name)
                .group_by(model.company_code, model.name)
                .having(_dkss_common.db.func.count(model.id) > 1)
                .first()
            )
            if duplicate:
                raise RuntimeError(f"{label}マスタに同一会社・同一名称の重複があります。")
            table = model.__tablename__
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_company_name "
                    f"ON {table} (company_code, name)"
                )
            )

        duplicate_vehicle_type = (
            _dkss_common.db.session.query(
                _dkss_models.VehicleType.company_code,
                _dkss_models.VehicleType.name
            )
            .group_by(
                _dkss_models.VehicleType.company_code,
                _dkss_models.VehicleType.name
            )
            .having(
                _dkss_common.db.func.count(_dkss_models.VehicleType.id) > 1
            )
            .first()
        )

        if duplicate_vehicle_type:
            raise RuntimeError(
                "車種マスタに同一会社・同一名称の重複があります。"
            )

        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_vehicle_type_company_name "
                "ON vehicle_type (company_code, name)"
            )
        )

        duplicate_vehicle_checklist_result = (
            _dkss_common.db.session.query(
                _dkss_models.VehicleChecklistResult.company_code,
                _dkss_models.VehicleChecklistResult.checklist_id,
                _dkss_models.VehicleChecklistResult.vehicle_record_id,
                _dkss_models.VehicleChecklistResult.year,
                _dkss_models.VehicleChecklistResult.month,
                _dkss_models.VehicleChecklistResult.day
            )
            .group_by(
                _dkss_models.VehicleChecklistResult.company_code,
                _dkss_models.VehicleChecklistResult.checklist_id,
                _dkss_models.VehicleChecklistResult.vehicle_record_id,
                _dkss_models.VehicleChecklistResult.year,
                _dkss_models.VehicleChecklistResult.month,
                _dkss_models.VehicleChecklistResult.day
            )
            .having(
                _dkss_common.db.func.count(_dkss_models.VehicleChecklistResult.id) > 1
            )
            .first()
        )

        if duplicate_vehicle_checklist_result:
            raise RuntimeError(
                "車両チェックリスト結果に同一会社・チェックリスト・"
                "車両・点検日の重複があります。"
            )

        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_vehicle_checklist_result_target_date "
                "ON vehicle_checklist_result "
                "(company_code, checklist_id, vehicle_record_id, "
                "year, month, day)"
            )
        )

        _dkss_common.db.session.commit()



def initialize_database():
    """Explicit compatibility migrations and bootstrap, never called on import."""
    init_db()
    with _dkss_runtime.app.app_context():

        _dkss_common.db.create_all()

        maintenance_columns = {
            column["name"]
            for column in _dkss_common.inspect(_dkss_common.db.engine).get_columns(
                "vehicle_maintenance_record"
            )
        }

        if "invoice_details_json" not in maintenance_columns:
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE vehicle_maintenance_record "
                    "ADD COLUMN invoice_details_json "
                    "TEXT NOT NULL DEFAULT '{}'"
                )
            )
            _dkss_common.db.session.commit()

        columns = [
            ("chassis_number", "VARCHAR(100)"),
            ("model_code", "VARCHAR(100)"),
            ("first_registration_date", "VARCHAR(20)"),
            ("manufacturer", "VARCHAR(100)"),
            ("body_type", "VARCHAR(100)"),
            ("gross_vehicle_weight", "INTEGER"),
            ("max_payload", "INTEGER"),
        ]

        inspector = _dkss_common.inspect(_dkss_common.db.engine)

        existing_columns = [
            column["name"]
            for column in inspector.get_columns("vehicle")
        ]

        for column_name, column_type in columns:
            if column_name not in existing_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE vehicle "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        if _dkss_common.db.engine.dialect.name == "postgresql":
            chassis_column = next(
                column for column in _dkss_common.inspect(_dkss_common.db.engine).get_columns("vehicle")
                if column["name"] == "chassis_number"
            )
            if not chassis_column["nullable"]:
                _dkss_common.db.session.execute(_dkss_common.db.text(
                    "ALTER TABLE vehicle "
                    "ALTER COLUMN chassis_number DROP NOT NULL"
                ))
                _dkss_common.db.session.commit()

        if (
            _dkss_common.db.engine.dialect.name == "postgresql"
            and "vehicle_id" in existing_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE vehicle "
                    "ALTER COLUMN vehicle_id DROP NOT NULL"
                )
            )
            _dkss_common.db.session.commit()

        if "vehicle_id" in existing_columns:
            for driver in _dkss_models.Driver.query.all():
                vehicle_ids = _dkss_serialization.safe_json_str_list(
                    driver.vehicles_json
                )

                converted_vehicle_ids = []

                for vehicle_id in vehicle_ids:
                    if str(vehicle_id).isdigit():
                        converted_vehicle_ids.append(
                            str(vehicle_id)
                        )
                        continue

                    vehicle_row = _dkss_common.db.session.execute(
                        _dkss_common.db.text(
                            """
                        SELECT id
                        FROM vehicle
                        WHERE company_code = :company_code
                          AND vehicle_id = :vehicle_id
                        LIMIT 1
                        """
                        ),
                        {
                            "company_code": driver.company_code,
                            "vehicle_id": vehicle_id,
                        }
                    ).first()

                    if vehicle_row:
                        converted_vehicle_ids.append(
                            str(vehicle_row.id)
                        )

                driver.vehicles_json = _dkss_common.json.dumps(
                    list(dict.fromkeys(converted_vehicle_ids)),
                    ensure_ascii=False
                )

            _dkss_common.db.session.commit()

        vehicle_patrol_columns = [
            ("vehicle_record_id", "INTEGER"),
        ]

        existing_vehicle_patrol_columns = [
            column["name"]
            for column in inspector.get_columns(
                "vehicle_patrol"
            )
        ]

        for column_name, column_type in vehicle_patrol_columns:
            if column_name not in existing_vehicle_patrol_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE vehicle_patrol "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        if (
            "vehicle_id" in existing_vehicle_patrol_columns
            and "vehicle_id" in existing_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    """
                UPDATE vehicle_patrol
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_patrol.company_code
                      AND vehicle.vehicle_id = vehicle_patrol.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
                )
            )

            _dkss_common.db.session.commit()

        vehicle_checklist_notify_setting_columns = [
            ("vehicle_record_id", "INTEGER"),
        ]

        existing_vehicle_checklist_notify_setting_columns = [
            column["name"]
            for column in inspector.get_columns(
                "vehicle_checklist_notify_setting"
            )
        ]

        if (
            _dkss_common.db.engine.dialect.name == "postgresql"
            and "vehicle_id" in existing_vehicle_checklist_notify_setting_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE vehicle_checklist_notify_setting "
                    "ALTER COLUMN vehicle_id DROP NOT NULL"
                )
            )
            _dkss_common.db.session.commit()

        for column_name, column_type in vehicle_checklist_notify_setting_columns:
            if column_name not in existing_vehicle_checklist_notify_setting_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE vehicle_checklist_notify_setting "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        if (
            "vehicle_id" in existing_vehicle_checklist_notify_setting_columns
            and "vehicle_id" in existing_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    """
                UPDATE vehicle_checklist_notify_setting
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_checklist_notify_setting.company_code
                      AND vehicle.vehicle_id = vehicle_checklist_notify_setting.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
                )
            )

            _dkss_common.db.session.commit()

        # News テナント分離

        inspector = _dkss_common.inspect(_dkss_common.db.engine)

        news_columns = [
            column["name"]
            for column in inspector.get_columns("news")
        ]

        if "company_code" not in news_columns:
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE news "
                    "ADD COLUMN company_code VARCHAR(50)"
                )
            )

            _dkss_common.db.session.commit()

        # 既存のお知らせには会社情報が存在しないため、
        # 他社へ誤表示されないようITC所属として隔離する
        _dkss_common.db.session.execute(
            _dkss_common.db.text(
                "UPDATE news "
                "SET company_code = 'ITC' "
                "WHERE company_code IS NULL "
                "OR company_code = ''"
            )
        )

        _dkss_common.db.session.commit()

        checklist_columns = [
            ("notify_users_json", "TEXT"),
            ("version_history_json", "TEXT"),
            (
                "active",
                "BOOLEAN NOT NULL DEFAULT TRUE"
            ),
            (
                "print_portrait",
                "BOOLEAN NOT NULL DEFAULT FALSE"
            ),
            (
                "print_half_month",
                "BOOLEAN NOT NULL DEFAULT FALSE"
            ),
                    (
                "reminder_enabled",
                "BOOLEAN NOT NULL DEFAULT TRUE"
            ),
            (
                "reminder_time",
                "VARCHAR(5) NOT NULL DEFAULT '08:00'"
            ),
        ]

        existing_checklist_columns = [
            column["name"]
            for column in inspector.get_columns("checklist")
        ]

        for column_name, column_type in checklist_columns:
            if column_name not in existing_checklist_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE checklist "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        checklist_result_columns = [
            ("approvals_json", "TEXT"),
            ("notify_users_json", "TEXT"),
            ("target_username", "VARCHAR(50)"),
            ("target_vehicle_record_id", "INTEGER"),
            ("checked_by_username", "VARCHAR(50)"),
            ("approved_by_username", "VARCHAR(50)"),
            ("checklist_snapshot_json", "TEXT"),
        ]

        existing_checklist_result_columns = [
            column["name"]
            for column in inspector.get_columns(
                "checklist_result"
            )
        ]

        for column_name, column_type in checklist_result_columns:
            if column_name not in existing_checklist_result_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE checklist_result "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        checklist_result_column_names = {
            column["name"]
            for column in inspector.get_columns(
                "checklist_result"
            )
        }

        vehicle_column_names = {
            column["name"]
            for column in inspector.get_columns(
                "vehicle"
            )
        }

        if (
            "target_vehicle" in checklist_result_column_names
            and "vehicle_id" in vehicle_column_names
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    """
                UPDATE checklist_result
                SET target_vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = checklist_result.company_code
                      AND vehicle.vehicle_id = checklist_result.target_vehicle
                )
                WHERE target_type = 'vehicle'
                  AND target_vehicle_record_id IS NULL
                  AND target_vehicle IS NOT NULL
                  AND target_vehicle != ''
                """
                )
            )

            _dkss_common.db.session.commit()

        legacy_snapshot_results = (
            _dkss_models.ChecklistResult.query.filter(
                _dkss_common.db.or_(
                    _dkss_models.ChecklistResult.checklist_snapshot_json.is_(None),
                    _dkss_models.ChecklistResult.checklist_snapshot_json == ""
                )
            ).all()
        )

        for result in legacy_snapshot_results:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result.checklist_id,
                company_code=result.company_code
            ).first()

            if not checklist_record:
                continue

            checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

            checked_date = str(
                result.checked_date or ""
            )

            result_checklist = _dkss_checklist_common.checklist_for_date(
                checklist,
                checked_date[:4],
                checked_date[5:7],
                checked_date[8:10]
            )

            result.checklist_snapshot_json = _dkss_common.json.dumps(
                result_checklist,
                ensure_ascii=False
            )

        _dkss_common.db.session.commit()

        legacy_checked_results = _dkss_models.ChecklistResult.query.filter(
            _dkss_common.db.or_(
                _dkss_models.ChecklistResult.checked_by_username.is_(None),
                _dkss_models.ChecklistResult.checked_by_username == ""
            ),
            _dkss_models.ChecklistResult.checked_by.isnot(None),
            _dkss_models.ChecklistResult.checked_by != ""
        ).all()

        for checklist_result in legacy_checked_results:
            checked_by_name = str(
                checklist_result.checked_by or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == checklist_result.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == checked_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            checklist_result.checked_by_username = (
                matched_users[0].username
            )

        _dkss_common.db.session.commit()

        legacy_target_results = _dkss_models.ChecklistResult.query.filter(
            _dkss_models.ChecklistResult.target_type == "user",
            _dkss_common.db.or_(
                _dkss_models.ChecklistResult.target_username.is_(None),
                _dkss_models.ChecklistResult.target_username == ""
            ),
            _dkss_models.ChecklistResult.target_user.isnot(None),
            _dkss_models.ChecklistResult.target_user != ""
        ).all()

        for checklist_result in legacy_target_results:
            target_name = str(
                checklist_result.target_user or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == checklist_result.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == target_name
            ).all()

            if len(matched_users) != 1:
                continue

            checklist_result.target_username = (
                matched_users[0].username
            )

        _dkss_common.db.session.commit()

        legacy_approved_results = _dkss_models.ChecklistResult.query.filter(
            _dkss_common.db.or_(
                _dkss_models.ChecklistResult.approved_by_username.is_(None),
                _dkss_models.ChecklistResult.approved_by_username == ""
            ),
            _dkss_models.ChecklistResult.approved_by.isnot(None),
            _dkss_models.ChecklistResult.approved_by != ""
        ).all()

        for checklist_result in legacy_approved_results:
            approved_by_name = str(
                checklist_result.approved_by or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == checklist_result.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == approved_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            checklist_result.approved_by_username = (
                matched_users[0].username
            )

        _dkss_common.db.session.commit()

        legacy_approval_results = _dkss_models.ChecklistResult.query.filter(
            _dkss_models.ChecklistResult.approvals_json.isnot(None),
            _dkss_models.ChecklistResult.approvals_json != ""
        ).all()

        for checklist_result in legacy_approval_results:
            approvals = _dkss_serialization.safe_json_dict_list(
                checklist_result.approvals_json
            )

            changed = False

            for approval in approvals:
                if approval.get("approved_by_username"):
                    continue

                approved_by_name = str(
                    approval.get("approved_by") or ""
                ).strip()

                if not approved_by_name:
                    continue

                matched_users = _dkss_models.User.query.filter(
                    _dkss_models.User.company_code == checklist_result.company_code,
                    (
                        _dkss_models.User.last_name
                        + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                    ) == approved_by_name
                ).all()

                if len(matched_users) != 1:
                    continue

                approval["approved_by_username"] = (
                    matched_users[0].username
                )
                changed = True

            if changed:
                checklist_result.approvals_json = _dkss_common.json.dumps(
                    approvals,
                    ensure_ascii=False
                )

        _dkss_common.db.session.commit()

        vehicle_checklist_result_columns = [
            ("operation_judgment_json", "TEXT"),
            ("notify_users_json", "TEXT"),
            ("approvals_json", "TEXT"),
            ("vehicle_record_id", "INTEGER"),
            ("checked_by_username", "VARCHAR(50)"),
            ("approved_by_username", "VARCHAR(50)"),
            ("checklist_snapshot_json", "TEXT"),
        ]

        existing_vehicle_checklist_result_columns = [
            column["name"]
            for column in inspector.get_columns(
                "vehicle_checklist_result"
            )
        ]

        for column_name, column_type in vehicle_checklist_result_columns:
            if column_name not in existing_vehicle_checklist_result_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE vehicle_checklist_result "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        vehicle_checklist_result_column_names = {
            column["name"]
            for column in inspector.get_columns(
                "vehicle_checklist_result"
            )
        }

        if (
            "vehicle_id" in vehicle_checklist_result_column_names
            and "vehicle_id" in vehicle_column_names
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    """
                UPDATE vehicle_checklist_result
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_checklist_result.company_code
                      AND vehicle.vehicle_id = vehicle_checklist_result.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
                )
            )

            _dkss_common.db.session.commit()

        legacy_vehicle_snapshot_results = (
            _dkss_models.VehicleChecklistResult.query.filter(
                _dkss_common.db.or_(
                    _dkss_models.VehicleChecklistResult.checklist_snapshot_json.is_(None),
                    _dkss_models.VehicleChecklistResult.checklist_snapshot_json == ""
                )
            ).all()
        )

        for result in legacy_vehicle_snapshot_results:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result.checklist_id,
                company_code=result.company_code
            ).first()

            if not checklist_record:
                continue

            checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

            result_checklist = _dkss_checklist_common.checklist_for_date(
                checklist,
                result.year,
                result.month,
                result.day
            )

            result.checklist_snapshot_json = _dkss_common.json.dumps(
                result_checklist,
                ensure_ascii=False
            )

        _dkss_common.db.session.commit()

        legacy_vehicle_checked_results = (
            _dkss_models.VehicleChecklistResult.query.filter(
                _dkss_common.db.or_(
                    _dkss_models.VehicleChecklistResult.checked_by_username.is_(None),
                    _dkss_models.VehicleChecklistResult.checked_by_username == ""
                ),
                _dkss_models.VehicleChecklistResult.checked_by.isnot(None),
                _dkss_models.VehicleChecklistResult.checked_by != ""
            ).all()
        )

        for result in legacy_vehicle_checked_results:
            checked_by_name = str(
                result.checked_by or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == result.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == checked_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            result.checked_by_username = (
                matched_users[0].username
            )

        legacy_vehicle_approved_results = (
            _dkss_models.VehicleChecklistResult.query.filter(
                _dkss_common.db.or_(
                    _dkss_models.VehicleChecklistResult.approved_by_username.is_(None),
                    _dkss_models.VehicleChecklistResult.approved_by_username == ""
                ),
                _dkss_models.VehicleChecklistResult.approved_by.isnot(None),
                _dkss_models.VehicleChecklistResult.approved_by != ""
            ).all()
        )

        for result in legacy_vehicle_approved_results:
            approved_by_name = str(
                result.approved_by or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == result.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == approved_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            result.approved_by_username = (
                matched_users[0].username
            )

        vehicle_approval_results = (
            _dkss_models.VehicleChecklistResult.query.filter(
                _dkss_models.VehicleChecklistResult.approvals_json.isnot(None),
                _dkss_models.VehicleChecklistResult.approvals_json != ""
            ).all()
        )

        for result in vehicle_approval_results:
            approvals = _dkss_serialization.safe_json_dict_list(
                result.approvals_json
            )

            changed = False

            for approval in approvals:
                if approval.get("approved_by_username"):
                    continue

                approved_by_name = str(
                    approval.get("approved_by") or ""
                ).strip()

                if not approved_by_name:
                    continue

                matched_users = _dkss_models.User.query.filter(
                    _dkss_models.User.company_code == result.company_code,
                    (
                        _dkss_models.User.last_name
                        + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                    ) == approved_by_name
                ).all()

                if len(matched_users) != 1:
                    continue

                approval["approved_by_username"] = (
                    matched_users[0].username
                )
                changed = True

            if changed:
                result.approvals_json = _dkss_common.json.dumps(
                    approvals,
                    ensure_ascii=False
                )

        _dkss_common.db.session.commit()

        user_columns = [
            (
                "first_name",
                "VARCHAR(100)"
            ),
            (
                "timezone",
                "VARCHAR(100) NOT NULL DEFAULT 'Asia/Tokyo'"
            ),
            (
                "email_address",
                "VARCHAR(255)"
            ),
            (
                "email_notify_enabled",
                "BOOLEAN NOT NULL DEFAULT FALSE"
            ),
                    (
                "failed_login_count",
                "INTEGER NOT NULL DEFAULT 0"
            ),
            (
                "login_locked",
                "BOOLEAN NOT NULL DEFAULT FALSE"
            ),
                    (
                "password_history_json",
                "TEXT NOT NULL DEFAULT '[]'"
            ),
                    (
                "password_changed_at",
                "VARCHAR(20)"
            ),
                    (
                "last_login_at",
                "VARCHAR(20)"
            ),
                    (
                "mfa_code_hash",
                "VARCHAR(255)"
            ),
            (
                "mfa_code_expires_at",
                "VARCHAR(20)"
            ),
            (
                "mfa_code_sent_at",
                "VARCHAR(20)"
            ),
            (
                "pending_email_address",
                "VARCHAR(255)"
            ),
            (
                "email_change_code_hash",
                "VARCHAR(255)"
            ),
            (
                "email_change_code_expires_at",
                "VARCHAR(20)"
            ),
            (
                "profile_image",
                "VARCHAR(255)"
            ),
            ("dashboard_settings_json", "TEXT DEFAULT '{}'")
        ]

        existing_user_columns = [
            column["name"]
            for column in inspector.get_columns("user")
        ]

        for column_name, column_type in user_columns:
            if column_name not in existing_user_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f'ALTER TABLE "user" '
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        _dkss_common.db.session.commit()

        notification_columns = [
            ("company_code", "VARCHAR(50)"),
            ("target_username", "VARCHAR(50)"),
            ("deleted_at", "TIMESTAMP"),
            ("workflow_context_json", "TEXT DEFAULT '{}'"),
        ]

        inspector = _dkss_common.inspect(_dkss_common.db.engine)

        existing_patrol_result_columns = [
            column["name"]
            for column in inspector.get_columns(
                "patrol_result"
            )
        ]

        if (
            "target_username"
            not in existing_patrol_result_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE patrol_result "
                    "ADD COLUMN target_username VARCHAR(50)"
                )
            )

            _dkss_common.db.session.commit()
        if (
            "countermeasure_by_username"
            not in existing_patrol_result_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE patrol_result "
                    "ADD COLUMN countermeasure_by_username VARCHAR(50)"
                )
            )

            _dkss_common.db.session.commit()

        if (
            "countermeasure_files_json"
            not in existing_patrol_result_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE patrol_result "
                    "ADD COLUMN countermeasure_files_json TEXT"
                )
            )

            _dkss_common.db.session.commit()

        if (
            "countermeasure_due_date"
            not in existing_patrol_result_columns
        ):
            _dkss_common.db.session.execute(
                _dkss_common.db.text(
                    "ALTER TABLE patrol_result "
                    "ADD COLUMN countermeasure_due_date VARCHAR(20)"
                )
            )

            _dkss_common.db.session.commit()

        legacy_patrol_results = _dkss_models.PatrolResult.query.filter(
            _dkss_models.PatrolResult.target_type == "user",
            _dkss_common.db.or_(
                _dkss_models.PatrolResult.target_username.is_(None),
                _dkss_models.PatrolResult.target_username == ""
            )
        ).all()

        for patrol_result in legacy_patrol_results:
            target_name = str(
                patrol_result.target_user or ""
            ).strip()

            if not target_name:
                continue

            matched_drivers = _dkss_models.Driver.query.filter_by(
                company_code=patrol_result.company_code,
                name=target_name
            ).all()

            if len(matched_drivers) != 1:
                continue

            matched_user = _dkss_models.User.query.filter_by(
                company_code=patrol_result.company_code,
                username=matched_drivers[0].employee_id
            ).first()

            if not matched_user:
                continue

            patrol_result.target_username = (
                matched_user.username
            )

        _dkss_common.db.session.commit()

        legacy_countermeasure_results = _dkss_models.PatrolResult.query.filter(
            _dkss_common.db.or_(
                _dkss_models.PatrolResult.countermeasure_by_username.is_(None),
                _dkss_models.PatrolResult.countermeasure_by_username == ""
            ),
            _dkss_models.PatrolResult.countermeasure_by.isnot(None),
            _dkss_models.PatrolResult.countermeasure_by != ""
        ).all()

        for patrol_result in legacy_countermeasure_results:
            countermeasure_name = str(
                patrol_result.countermeasure_by or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter_by(
                company_code=patrol_result.company_code,
                name=countermeasure_name
            ).all()

            if len(matched_users) != 1:
                continue

            patrol_result.countermeasure_by_username = (
                matched_users[0].username
            )

        _dkss_common.db.session.commit()

        existing_notification_columns = [
            column["name"]
            for column in inspector.get_columns(
                "notification"
            )
        ]

        for column_name, column_type in notification_columns:
            if column_name not in existing_notification_columns:
                _dkss_common.db.session.execute(
                    _dkss_common.db.text(
                        f"ALTER TABLE notification "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

            _dkss_common.db.session.commit()

        legacy_notifications = _dkss_models.Notification.query.filter(
            _dkss_common.db.or_(
                _dkss_models.Notification.target_username.is_(None),
                _dkss_models.Notification.target_username == ""
            ),
            _dkss_models.Notification.target_user.isnot(None),
            _dkss_models.Notification.target_user != ""
        ).all()

        for notification in legacy_notifications:
            target_name = str(
                notification.target_user or ""
            ).strip()

            matched_users = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == notification.company_code,
                (
                    _dkss_models.User.last_name
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ) == target_name
            ).all()

            if len(matched_users) != 1:
                continue

            notification.target_username = (
                matched_users[0].username
            )

        _dkss_common.db.session.commit()
