"""運行実績CSVの読取り・入力検証。Flask・DB・外部APIに依存しない。"""

import csv
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from upload_validation import UploadValidationError


def normalize_vehicle_operation_plate(value):
    import unicodedata

    text = unicodedata.normalize(
        "NFKC",
        "" if value is None else str(value)
    ).strip()

    return re.sub(
        r"[\s\-‐‑‒–—―−・･.]+",
        "",
        text
    ).casefold()

def parse_vehicle_operation_csv_row(source_row, line_number):
    try:
        report_number = source_row.get("日報番号", "").strip()

        if not report_number:
            raise UploadValidationError(
                "日報番号がありません。"
            )

        if len(report_number) > 100:
            raise UploadValidationError(
                "日報番号は100文字以内にしてください。"
            )

        operation_date = parse_vehicle_operation_date(
            source_row.get("運行日"),
            "運行日"
        )

        if operation_date is None:
            raise UploadValidationError(
                "運行日がありません。"
            )

        values = {
            "report_number": report_number,
            "operation_date": operation_date,
            "source_row_json": json.dumps(
                source_row,
                ensure_ascii=False
            ),
        }

        for csv_name, field_name in (
            ("車両コード", "source_vehicle_code"),
            ("車両", "source_vehicle_number"),
        ):
            text = source_row.get(csv_name, "").strip()

            if len(text) > 100:
                raise UploadValidationError(
                    f"{csv_name}は100文字以内にしてください。"
                )

            values[field_name] = text or None

        for csv_name, field_name in (
            ("出庫日時", "departure_at"),
            ("入庫日時", "arrival_at"),
        ):
            values[field_name] = parse_vehicle_operation_date(
                source_row.get(csv_name),
                csv_name,
                with_time=True
            )

        for csv_name, field_name in (
            ("出庫メータ", "departure_meter"),
            ("入庫メータ", "arrival_meter"),
            ("走行距離", "distance"),
        ):
            values[field_name] = parse_vehicle_operation_decimal(
                source_row.get(csv_name),
                csv_name
            )

        return values

    except UploadValidationError as error:
        raise UploadValidationError(
            f"CSVの{line_number}行目：{error}"
        ) from error

def read_vehicle_operation_csv(file_bytes):
    csv_text = None

    for encoding in ("utf-8-sig", "cp932"):
        try:
            csv_text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if csv_text is None:
        raise UploadValidationError(
            "CSVの文字コードを確認してください。"
        )

    if "\x00" in csv_text:
        raise UploadValidationError(
            "CSVファイルの内容が不正です。"
        )

    rows = []

    try:
        reader = csv.reader(
            StringIO(csv_text, newline=""),
            strict=True
        )
        headers = [
            value.strip()
            for value in next(reader, [])
        ]

        if not headers or any(not value for value in headers):
            raise UploadValidationError(
                "CSVの先頭行に項目名を設定してください。"
            )

        if len(headers) != len(set(headers)):
            raise UploadValidationError(
                "CSVの項目名が重複しています。"
            )

        missing_headers = [
            name
            for name in ("日報番号", "運行日")
            if name not in headers
        ]

        if missing_headers:
            raise UploadValidationError(
                "CSVに必要な項目がありません："
                + "、".join(missing_headers)
            )

        if not any(
            name in headers
            for name in ("車両コード", "車両")
        ):
            raise UploadValidationError(
                "CSVに車両コードまたは車両の項目が必要です。"
            )

        for values in reader:
            if not any(value.strip() for value in values):
                continue

            if len(values) != len(headers):
                raise UploadValidationError(
                    f"CSVの{reader.line_num}行目の列数が"
                    "項目名の列数と一致していません。"
                )

            rows.append({
                "line_number": reader.line_num,
                "source_row": dict(zip(headers, values)),
            })

    except csv.Error:
        raise UploadValidationError(
            "CSVの区切り文字・引用符を確認してください。"
        )

    if not rows:
        raise UploadValidationError(
            "CSVに運行実績のデータがありません。"
        )

    return rows

def parse_vehicle_operation_date(value, field_name, with_time=False):
    text = "" if value is None else str(value).strip()

    if not text:
        return None

    if with_time:
        formats = (
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
        )
        output_format = "%Y-%m-%d %H:%M:%S"
    else:
        formats = (
            "%Y/%m/%d",
            "%Y-%m-%d",
        )
        output_format = "%Y-%m-%d"

    for date_format in formats:
        try:
            parsed = datetime.strptime(text, date_format)
        except ValueError:
            continue

        return parsed.strftime(output_format)

    raise UploadValidationError(
        f"{field_name}の日付・時刻を確認してください。"
    )

def parse_vehicle_operation_decimal(value, field_name):
    text = "" if value is None else str(value).strip()

    if not text:
        return None

    if not re.fullmatch(
        r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?",
        text
    ):
        raise UploadValidationError(
            f"{field_name}は0以上の数値で入力してください。"
        )

    try:
        parsed = Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise UploadValidationError(
            f"{field_name}の数値を確認してください。"
        )

    if not parsed.is_finite() or parsed > Decimal("999999999999.99"):
        raise UploadValidationError(
            f"{field_name}の値が大きすぎます。"
        )

    try:
        rounded = parsed.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise UploadValidationError(
            f"{field_name}の数値を確認してください。"
        )

    if parsed != rounded:
        raise UploadValidationError(
            f"{field_name}は小数点以下2桁までで入力してください。"
        )

    return rounded
