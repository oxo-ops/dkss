"""車検証AIの結果を既存の車両登録フォーム用に変換する。DB更新なし。"""

from vehicle_certificate_ai import FIELDS


FORM_FIELDS = FIELDS + ("office",)


def prepare_certificate_form(extraction, vehicle_type_names):
    """AI抽出候補から既存登録フォームの初期値を生成する。"""

    if not isinstance(extraction, dict):
        raise ValueError("INVALID_CERTIFICATE_RESULT")

    source = extraction.get("vehicle")
    if not isinstance(source, dict):
        raise ValueError("INVALID_CERTIFICATE_VEHICLE")

    if not isinstance(vehicle_type_names, (list, tuple, set)):
        raise ValueError("INVALID_VEHICLE_TYPES")

    form = {}

    for field in FIELDS:
        value = source.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"INVALID_FIELD: {field}")
        form[field] = value or ""

    warnings = list(extraction.get("warnings") or [])

    if any(not isinstance(item, str) for item in warnings):
        raise ValueError("INVALID_WARNINGS")

    # 営業所は車検証から分からない。会社内のマスターから選択する。
    form["office"] = ""

    # 車種と営業所は会社内のマスターから利用者が選択する。
    form["type"] = ""

    # 原本の年月精度を保持する。実在しない日を補完しない。
    first_date = form["first_registration_date"]
    if first_date:
        from datetime import date
        import re
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}", first_date):
            year, month = map(int, first_date.split("-"))
            if not (1 <= year <= 9999 and 1 <= month <= 12):
                raise ValueError("INVALID_FIRST_REGISTRATION_MONTH")
        else:
            try:
                parsed = date.fromisoformat(first_date)
                if parsed.isoformat() != first_date:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("INVALID_FIRST_REGISTRATION_MONTH") from None
            form["first_registration_date"] = first_date[:7]

    # 確認画面を通らずに登録するための値は生成しない。
    form.pop("vehicle_form_action", None)

    return {
        "form": form,
        "warnings": warnings,
        "needs_review": True,
    }
